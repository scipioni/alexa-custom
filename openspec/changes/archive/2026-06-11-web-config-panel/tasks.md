## 1. Backend Dependencies and Setup

- [x] 1.1 Add `ruamel.yaml` to project dependencies (requirements.txt or pyproject.toml)
- [x] 1.2 Import ruamel.yaml in web.py and initialize Yaml() instance
- [x] 1.3 Create helper functions for reading/writing config with ruamel.yaml
- [x] 1.4 Implement config validation utility functions

## 2. Configuration API Endpoints

- [x] 2.1 Implement GET /api/config endpoint to return current config as JSON
- [x] 2.2 Implement POST /api/config endpoint for partial configuration updates
- [x] 2.3 Implement PUT /api/config endpoint for full configuration overwrite
- [x] 2.4 Add configuration validation for wake words (non-empty strings)
- [x] 2.5 Add configuration validation for timeout values (positive numbers)
- [x] 2.6 Implement file locking mechanism for concurrent edit protection
- [x] 2.7 Add temporary file writing with atomic rename for safe updates
- [x] 2.8 Integrate ConfigManager trigger on successful configuration save
- [x] 2.9 Add error handling for permission denied and file I/O failures
- [x] 2.10 Add error handling for ConfigManager hot-reload failures

## 3. Frontend Settings Panel

- [x] 3.1 Add "Settings" tab/panel to dashboard.html
- [x] 3.2 Create form layout for wake words input field
- [x] 3.3 Create form layout for threshold input fields
- [x] 3.4 Create form layout for timeout input field
- [x] 3.5 Implement save button with loading state indicator
- [x] 3.6 Implement cancel/reset button functionality
- [x] 3.7 Add success toast notification on save
- [x] 3.8 Add error toast notification on validation failure
- [x] 3.9 Implement form population with current config values
- [x] 3.10 Add input validation visual feedback (highlight invalid fields)

## 4. Integration and Testing

- [x] 4.1 Test GET /api/config returns complete configuration
- [x] 4.2 Test POST /api/config updates only specified fields
- [x] 4.3 Test PUT /api/config overwrites entire configuration
- [x] 4.4 Test configuration hot-reload triggers after API save
- [x] 4.5 Verify config.yaml comments and formatting are preserved
- [x] 4.6 Test error handling for invalid wake word format
- [x] 4.7 Test error handling for invalid timeout values
- [x] 4.8 Test error handling for permission denied scenario
- [x] 4.9 Test Settings panel loads and displays current config
- [x] 4.10 Test Settings panel save functionality with valid inputs
- [x] 4.11 Test Settings panel shows error on invalid inputs
- [x] 4.12 Test Settings panel cancel resets to previous values
- [x] 4.13 Verify concurrent API edit protection mechanism works

## 5. Enhanced Wake Word Management

- [x] 5.1 Implement wake word list display with individual items
- [x] 5.2 Add delete button for each wake word
- [x] 5.3 Implement add wake word functionality
- [x] 5.4 Store wake words as array of objects with aliases
- [x] 5.5 Add visual feedback for wake word operations
- [x] 5.6 Handle empty wake word list state

## 6. Documentation and Deployment

- [x] 6.1 Update user documentation with configuration panel usage
- [x] 6.2 Update AGENTS.md with configuration panel entry points
- [x] 6.3 Update CHANGELOG.md with new features
- [x] 6.4 Add screenshots or examples of configuration panel
- [x] 6.5 Prepare release notes for configuration panel feature