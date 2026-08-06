## ADDED Requirements

### Requirement: Wheel build automation per project
The system SHALL provide a Taskfile target in each publishable project
(`serena` root, `onvif_sua`) that builds a wheel and sdist for that project's
current `pyproject.toml` version into `dist/`.

#### Scenario: Building the root alexa-custom package
- **WHEN** a maintainer runs `task build` in the root `serena` repo
- **THEN** a wheel and sdist matching the current `pyproject.toml` version are produced in `dist/`

#### Scenario: Building onvif-sua
- **WHEN** a maintainer runs `task build` in `onvif_sua`
- **THEN** a wheel and sdist matching the current `pyproject.toml` version are produced in `dist/`, and `requirements.lock` is refreshed as it is today

### Requirement: Publish to a private PyPI-compatible registry
The system SHALL provide a Taskfile target per project that publishes the
project's built wheel and sdist to a configured private PyPI-compatible
registry, authenticated with credentials that are never committed to the
repository.

#### Scenario: Publishing with valid credentials configured
- **WHEN** a maintainer runs the publish task with `conf/secrets.yaml`'s `pypi:` block populated (`index_url`, `username`, `password`)
- **THEN** the built wheel and sdist are uploaded to `index_url`, authenticated with the configured username/password

#### Scenario: Publishing without credentials fails before any upload
- **WHEN** a maintainer runs the publish task and `conf/secrets.yaml` has no `pypi:` block or is missing required fields
- **THEN** the task fails immediately with an explicit "missing pypi credentials" error, before attempting any network request

### Requirement: Registry-agnostic publish/install tooling
The publish and install tooling SHALL work against any PyPI-compatible
"simple" index (e.g. a Gitea package registry or a GitLab package registry)
without any registry-specific code path.

#### Scenario: Switching the target registry
- **WHEN** `conf/secrets.yaml`'s `pypi.index_url` is changed to point at a different PyPI-compatible registry (e.g. from a Gitea instance to a GitLab instance)
- **THEN** the publish task succeeds with no code or Taskfile change, only the config value differing

### Requirement: Published versions come from the existing release flow
Published package versions SHALL always equal the project's current
`pyproject.toml` version field, which is bumped exclusively by the existing
`release:patch`/`release:minor`/`release:major` tasks — the publish task
itself SHALL NOT modify the version.

#### Scenario: Publishing a version bumped by the release flow
- **WHEN** `task release:patch` has bumped `pyproject.toml`'s version from `0.4.1` to `0.4.2`, and a maintainer then runs the publish task
- **THEN** the uploaded artifact is tagged version `0.4.2`

#### Scenario: Re-publishing an already-published version
- **WHEN** a maintainer runs the publish task again without an intervening version bump
- **THEN** the task either no-ops or fails with the registry's "version already exists" error, and does not silently overwrite the existing release artifact

### Requirement: Credentials are never committed
Registry credentials SHALL be readable only from a git-ignored location
(`conf/secrets.yaml`) at task run time, and SHALL NOT appear hardcoded in
`Taskfile.yml`, `pyproject.toml`, or any other committed file.

#### Scenario: Inspecting the publish task definition
- **WHEN** the publish task's `Taskfile.yml` definition is inspected
- **THEN** it contains no literal username, password, or token — only a runtime read of `conf/secrets.yaml`
