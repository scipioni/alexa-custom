## ADDED Requirements

### Requirement: Secrets are sourced from a .env file loaded in both run modes

The service SHALL read its three secrets — the camera common credential, the manual-scan credential, and the web GUI login password — from environment variables that are auto-loaded from a `.env` file at startup. Loading SHALL work identically in native (`uv run onvif-sua`) execution, via `python-dotenv`, and in Docker, via `env_file: .env` in `docker-compose.yml`. Environment variables already set in the process environment SHALL take precedence over values in `.env` (dotenv MUST NOT override an explicitly-exported variable). A committed `.env.example` SHALL document every secret variable.

#### Scenario: Native run loads .env

- **WHEN** the service starts via `uv run onvif-sua` with a `.env` file present in the working directory
- **THEN** the values in `.env` are available as environment variables before configuration is resolved

#### Scenario: Docker run loads .env

- **WHEN** the service starts via Docker Compose with `env_file: .env` configured
- **THEN** the same secret variables are present in the container environment

#### Scenario: Exported variable wins over .env

- **WHEN** a secret variable is already exported in the process environment and also present in `.env`
- **THEN** the exported value is used and the `.env` value is ignored

### Requirement: Camera common credential comes from the environment only

The camera common credential used by the persistent static workers SHALL be sourced from `CAMERA_USER` (defaulting to `admin` when unset) and `CAMERA_PASSWORD`. This credential SHALL NOT be read from or written to `settings.yaml`. The `settings.yaml` `cameras` block SHALL retain only non-secret fields — the camera `port` and the camera `list` (ip/name entries). Saving configuration from the GUI SHALL NOT write the camera password to `settings.yaml`.

#### Scenario: Camera credential resolved from env

- **WHEN** `CAMERA_USER` and `CAMERA_PASSWORD` are set in `.env`
- **THEN** the static workers authenticate with that user and password

#### Scenario: Camera user defaults to admin

- **WHEN** `CAMERA_PASSWORD` is set but `CAMERA_USER` is not
- **THEN** the camera user is `admin`

#### Scenario: Camera password is never persisted to settings.yaml

- **WHEN** the service saves `settings.yaml` (at boot or from a GUI action)
- **THEN** no camera password appears in the file; only the camera `port` and `list` remain in the `cameras` block

### Requirement: Manual-scan credential comes from the environment only

The manual subnet scan credential SHALL be sourced from `SCAN_USER` and `SCAN_PASSWORD`. When either is unset, it SHALL default to the corresponding camera credential value (`CAMERA_USER` / `CAMERA_PASSWORD`). The `scan.credentials` block SHALL NOT be present in `settings.yaml`, and the scan credential SHALL NOT be editable from the web GUI.

#### Scenario: Scan credential resolved from env

- **WHEN** `SCAN_USER` and `SCAN_PASSWORD` are set
- **THEN** the manual scan probes with that credential

#### Scenario: Scan credential defaults to the camera credential

- **WHEN** `SCAN_PASSWORD` is unset
- **THEN** the manual scan uses `CAMERA_PASSWORD` (and `CAMERA_USER` when `SCAN_USER` is also unset)

#### Scenario: GUI cannot edit scan credentials

- **WHEN** a client submits `cam_credentials` to `POST /api/config`
- **THEN** the field is ignored (not persisted), and the settings page no longer presents a scan-credentials form

### Requirement: Web login password comes from the environment only

The web GUI login password SHALL be sourced solely from `GUI_PASSWORD` (plaintext) and hashed in memory at load using the existing PBKDF2 hashing. It SHALL NOT be read from or written to `settings.yaml`. The in-GUI change-password flow SHALL be removed: `POST /api/change-password` SHALL no longer exist, and the settings page SHALL NOT present a change-password form. To change the login password, an operator edits `.env` and restarts.

#### Scenario: Login uses GUI_PASSWORD

- **WHEN** the service starts with `GUI_PASSWORD` set
- **THEN** logging in with the `GUI_PASSWORD` value succeeds and any other password is rejected

#### Scenario: Old web.password hash is ignored

- **WHEN** a legacy `settings.yaml` still contains a `web.password` hash after upgrade
- **THEN** it is not used for authentication and is stripped from `settings.yaml` on the next save

#### Scenario: No change-password endpoint or form

- **WHEN** a client requests `POST /api/change-password`, or the settings page is loaded
- **THEN** the endpoint does not exist (returns not-found) and no change-password form is shown

### Requirement: Placeholder-password safety guard evaluates the env-sourced secrets

The placeholder-password guard SHALL treat a camera or scan password equal to the sentinel `default_to_change` (or unset) as "not yet configured": while true, the camera workers and the manual subnet scan SHALL remain suppressed, exactly as before, but now evaluating the `.env`-sourced camera and scan passwords rather than `settings.yaml` values. `GET /api/status` SHALL continue to expose the placeholder flags for `cameras` and `scan`.

#### Scenario: Placeholder camera password suppresses workers

- **WHEN** `CAMERA_PASSWORD` is unset or equals `default_to_change`
- **THEN** the placeholder flag for `cameras` is true and no camera worker attempts to connect

#### Scenario: Placeholder scan password suppresses the manual scan

- **WHEN** the effective scan password is unset or equals `default_to_change`
- **THEN** the placeholder flag for `scan` is true and a manual rescan is refused

#### Scenario: Real passwords clear the guard

- **WHEN** both the camera and scan passwords are set to real (non-sentinel) values
- **THEN** both placeholder flags are false and workers/scan operate normally
