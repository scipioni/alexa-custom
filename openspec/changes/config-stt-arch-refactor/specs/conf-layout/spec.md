## ADDED Requirements

### Requirement: conf/ directory structure
The system SHALL store all configuration under a `conf/` directory at the project root. The directory SHALL contain `secrets.yaml`, `config.yaml`, and an `actions/` sub-directory. Example and template files MAY also be present (`secrets.yaml.example`, `config.yaml.example`). The previous root-level `config.yaml` and `actions.yaml` SHALL be removed.

#### Scenario: conf/ directory present at startup
- **WHEN** the daemon starts and `conf/config.yaml` exists
- **THEN** configuration is loaded from `conf/config.yaml` and the root-level `config.yaml` is not read

#### Scenario: conf/actions/ directory present
- **WHEN** `conf/actions/` exists and contains `.yaml` files
- **THEN** all files are loaded as action files per the multi-action-files capability

#### Scenario: Missing conf/ directory
- **WHEN** neither `conf/config.yaml` nor a legacy root-level `config.yaml` exists
- **THEN** the daemon starts with no triggers and logs a warning that no config was found

### Requirement: .gitignore excludes secrets.yaml
The project `.gitignore` SHALL contain an entry excluding `conf/secrets.yaml` from version control. `conf/secrets.yaml.example` SHALL be tracked.

#### Scenario: secrets.yaml not committed
- **WHEN** a developer runs `git status` after creating `conf/secrets.yaml`
- **THEN** the file does not appear in the staged or unstaged change list
