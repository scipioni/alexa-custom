## 1. Backend Dependencies and Setup

- [ ] 1.1 Add `ruamel.yaml` to project dependencies (requirements.txt or pyproject.toml)
- [ ] 1.2 Import ruamel.yaml in web.py and initialize Yaml() instance
- [ ] 1.3 Create helper functions for reading/writing config with ruamel.yaml
- [ ] 1.4 Implement config validation utility functions

## 2. Configuration API Endpoints

- [ ] 2.1 Implement GET /api/config endpoint to return current config as JSON
- [ ] 2.2 Implement POST /api/config endpoint for partial configuration updates
- [ ] 2.3 Implement PUT /api/config endpoint for full configuration overwrite
- [ ] 2.4 Add configuration validation for wake words (non-empty strings)
- [ ] 2.5 Add configuration validation for timeout values (positive numbers)
- [ ] 2.6 Implement file locking mechanism for concurrent edit protection
- [ ] 2.7 Add temporary file writing with atomic rename for safe updates
- [ ] 2.8 Integrate ConfigManager trigger on successful configuration save
- [ ] 2.9 Add error handling for permission denied and file I/O failures
- [ ] 2.10 Add error handling for ConfigManager hot-reload failures

## 3. Frontend Settings Panel

- [ ] 3.1 Add "Settings" tab/panel to dashboard.html
- [ ] 3.2 Create form layout for wake words input field
- [ ] 3.3 Create form layout for threshold input fields
- [ ] 3.4 Create form layout for timeout input field
- [ ] 3.5 Implement save button with loading state indicator
- [ ] 3.6 Implement cancel/reset button functionality
- [ ] 3.7 Add success toast notification on save
- [ ] 3.8 Add error toast notification on validation failure
- [ ] 3.9 Implement form population with current config values
- [ ] 3.10 Add input validation visual feedback (highlight invalid fields)

## 4. Integration and Testing

- [ ] 4.1 Test GET /api/config returns complete configuration
- [ ] 4.2 Test POST /api/config updates only specified fields
- [ ] 4.3 Test PUT /api/config overwrites entire configuration
- [ ] 4.4 Test configuration hot-reload triggers after API save
- [ ] 4.5 Verify config.yaml comments and formatting are preserved
- [ ] 4.6 Test error handling for invalid wake word format
- [ ] 4.7 Test error handling for invalid timeout values
- [ ] 4.8 Test error handling for permission denied scenario
- [ ] 4.9 Test Settings panel loads and displays current config
- [ ] 4.10 Test Settings panel save functionality with valid inputs
- [ ] 4.11 Test Settings panel shows error on invalid inputs
- [ ] 4.12 Test Settings panel cancel resets to previous values
- [ ] 4.13 Verify concurrent API edit protection mechanism works