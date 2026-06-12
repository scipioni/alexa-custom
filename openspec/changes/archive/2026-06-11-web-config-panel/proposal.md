## Why

Administrators currently need SSH access to view and update system configurations (wake words, thresholds, timeouts) — an inconvenient workflow that increases error risk. The Web UI already provides monitoring capabilities; adding configuration management would complete the admin control panel with direct, user-friendly access.

## What Changes

- Add HTTP API endpoints to `web.py` for `GET /api/config` (fetch current config) and `POST/PUT /api/config` (update config)
- Integrate `ruamel.yaml` to parse and update `config.yaml` while preserving comments and formatting
- Connect API updates to `ConfigManager` to trigger automatic configuration hot-reloads on save
- Create new Settings panel/tab in `dashboard.html` with form inputs for config values
- Add success/error feedback indicators (toasts/messages) when saving configuration changes

## Capabilities

### New Capabilities
- `web-config-api`: HTTP endpoints for configuration management
- `web-config-ui`: Settings panel in dashboard for viewing/updating configuration

### Modified Capabilities
None — existing `web.py` and `ConfigManager` APIs are extended; no requirement changes to existing capabilities.

## Impact

- **Affected code**: `web.py`, `config.yaml`, `dashboard.html`
- **New dependencies**: `ruamel.yaml` (add to requirements)
- **New API endpoints**: `GET /api/config`, `POST /api/config`, `PUT /api/config`
- **New UI components**: Settings panel with text inputs, number fields, checkboxes in dashboard
- **Integration**: ConfigManager hot-reload trigger on API save
- **User experience**: No SSH required for config updates; immediate UI feedback