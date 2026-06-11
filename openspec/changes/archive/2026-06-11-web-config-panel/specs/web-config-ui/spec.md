## ADDED Requirements

### Requirement: Settings panel in dashboard

The system SHALL provide a dedicated "Settings" panel or tab within the dashboard web interface for viewing and updating configuration.

#### Scenario: Administrator views settings panel
- **WHEN** an administrator navigates to the dashboard
- **THEN** the system displays the Settings panel with current configuration values

#### Scenario: Settings panel displays all configuration fields
- **WHEN** the Settings panel is rendered
- **THEN** the panel shows input fields for wake words, thresholds, and timeouts

### Requirement: Configuration form inputs

The Settings panel SHALL provide appropriate input controls for each configuration type.

#### Scenario: Wake words displayed as comma-separated text input
- **WHEN** the wake words field is rendered
- **THEN** the system displays a text input field with comma-separated wake word values

#### Scenario: Numeric thresholds displayed as number inputs
- **WHEN** threshold fields (e.g., command_timeout) are rendered
- **THEN** the system displays number input fields with current values

#### Scenario: Boolean flags displayed as checkboxes when applicable
- **WHEN** configuration includes boolean flags
- **THEN** the system displays checkboxes with current state

### Requirement: Save functionality with feedback

The Settings panel SHALL provide a save button that updates configuration with immediate user feedback.

#### Scenario: Administrator saves valid configuration
- **WHEN** an administrator clicks "Save" with valid values
- **THEN** the system displays a success message (toast)
- **AND** the configuration is updated via API
- **AND** the Settings panel refreshes with new values

#### Scenario: Administrator cancels unsaved changes
- **WHEN** an administrator clicks "Cancel" without saving
- **THEN** the Settings panel closes or resets to previous values

#### Scenario: Invalid input displays error feedback
- **WHEN** an administrator submits invalid configuration values
- **THEN** the system displays an error message (toast)
- **AND** the form remains in edit mode with invalid input highlighted

### Requirement: Loading states during save operations

The Settings panel SHALL indicate when configuration is being saved.

#### Scenario: Save button shows loading state during operation
- **WHEN** the save operation is in progress
- **THEN** the save button displays a loading indicator
- **AND** the save button is disabled during operation

#### Scenario: Loading state clears on completion or failure
- **WHEN** the save operation completes or fails
- **THEN** the loading indicator is removed
- **AND** the save button is re-enabled