## ADDED Requirements

### Requirement: HTTP endpoints for configuration retrieval

The system SHALL provide a GET endpoint at `/api/config` that returns the current configuration as JSON.

#### Scenario: Administrator fetches current configuration
- **WHEN** an administrator makes a GET request to `/api/config`
- **THEN** the system returns the complete configuration in JSON format including all fields from `config.yaml`

#### Scenario: Response includes all configuration fields
- **WHEN** the GET endpoint is called
- **THEN** the response includes all configuration values (wake_words, triggers, command_timeout, env)

### Requirement: HTTP endpoints for configuration updates

The system SHALL provide POST and PUT endpoints at `/api/config` to update configuration values.

#### Scenario: Administrator updates specific configuration values
- **WHEN** an administrator sends a POST request with partial configuration to `/api/config`
- **THEN** the system updates only the provided fields in `config.yaml`
- **AND** the system triggers ConfigManager hot-reload to apply changes immediately

#### Scenario: Administrator overwrites entire configuration
- **WHEN** an administrator sends a PUT request with full configuration to `/api/config`
- **THEN** the system replaces all existing configuration with the provided values
- **AND** the system triggers ConfigManager hot-reload to apply changes immediately

#### Scenario: Configuration update preserves comments and formatting
- **WHEN** configuration is updated via API endpoints
- **THEN** the system uses `ruamel.yaml` to preserve comments and formatting in `config.yaml`

### Requirement: Configuration validation

The system SHALL validate configuration values before applying updates.

#### Scenario: Invalid wake words are rejected
- **WHEN** an administrator provides an invalid wake word configuration
- **THEN** the system returns a 400 Bad Request error with validation details
- **AND** the configuration file is not modified

#### Scenario: Invalid timeout values are rejected
- **WHEN** an administrator provides timeout values outside valid range
- **THEN** the system returns a 400 Bad Request error with validation details
- **AND** the configuration file is not modified

### Requirement: Error handling for configuration operations

The system SHALL handle errors gracefully when configuration operations fail.

#### Scenario: Configuration file write failure
- **WHEN** the system cannot write to `config.yaml` (e.g., permission denied)
- **THEN** the system returns a 500 Internal Server Error
- **AND** the configuration file remains unchanged

#### Scenario: ConfigManager hot-reload failure
- **WHEN** ConfigManager fails to apply the updated configuration
- **THEN** the system returns a 500 Internal Server Error
- **AND** the configuration file remains unchanged
- **AND** the error is logged for administrator review