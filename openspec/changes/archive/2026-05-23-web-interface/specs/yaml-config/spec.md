## ADDED Requirements

### Requirement: Optional web section in config.yaml
The system SHALL support an optional top-level `web:` key in `config.yaml`. When present, it SHALL accept the following fields: `port` (integer, default `8080`) and `enabled` (boolean, default `false`). These values SHALL be accessible to the web interface module but SHALL NOT affect startup unless the `--web` CLI flag is explicitly passed.

#### Scenario: web.port read from config
- **WHEN** `config.yaml` contains `web: { port: 9090 }` and `--web` is passed
- **THEN** the HTTP server binds to port 9090 (CLI flag `--web-port` takes precedence if also provided)

#### Scenario: Missing web section uses defaults
- **WHEN** `config.yaml` has no `web:` key
- **THEN** the web interface uses port 8080 when started with `--web`
