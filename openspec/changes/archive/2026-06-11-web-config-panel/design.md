## Context

The Web UI provides monitoring and status dashboards but lacks configuration management capabilities. Currently, administrators must access the system via SSH to update `config.yaml`, which is error-prone and inconvenient. The system already has a ConfigManager for hot-reloading and an aiohttp web server in `web.py` that can be extended.

**Current State:**
- `config.yaml`: Single source of truth for system configuration
- `ConfigManager`: Hot-reloads configuration changes automatically
- `web.py`: aiohttp web server with existing endpoints (currently no config management)
- `dashboard.html`: Existing dashboard UI for monitoring

**Constraints:**
- Must preserve comments and formatting in `config.yaml` (ruamel.yaml required)
- Must integrate with existing ConfigManager for hot-reload
- Must not break existing web UI functionality
- No authentication/authorization layer specified (web UI should be firewalled in production)

## Goals / Non-Goals

**Goals:**
- Provide HTTP API endpoints for configuration retrieval and updates
- Create Settings panel in dashboard.html for UI-based configuration management
- Integrate with ConfigManager to trigger automatic hot-reloads on save
- Preserve `config.yaml` comments and formatting during updates

**Non-Goals:**
- Authentication/authorization for API endpoints (out of scope for this change)
- Configuration history/audit trail (can be added separately)
- Real-time configuration validation without user action
- Rollback mechanism for failed updates
- Multi-user configuration management

## Decisions

### 1. Use `ruamel.yaml` for configuration parsing and writing

**Rationale:** PyYAML loses comments and formatting. `ruamel.yaml` preserves structure and comments, which is critical for maintaining readable `config.yaml`.

**Alternatives Considered:**
- PyYAML with manual comment preservation: Too complex and error-prone
- JSON format: Loses comments and YAML-specific features (anchors, aliases)

### 2. Support both POST (partial updates) and PUT (full overwrite)

**Rationale:** POST allows administrators to update specific fields (e.g., only wake words) without affecting other configuration. PUT provides ability to completely replace configuration if needed.

**Alternatives Considered:**
- Only POST: Would require sending entire config for partial updates
- Only PUT: More complex client-side handling, no partial update convenience

### 3. Single file `config.yaml` with ConfigManager integration

**Rationale:** ConfigManager already handles hot-reloading from `config.yaml`. Adding API endpoints that write to the same file and call ConfigManager is the simplest integration path.

**Alternatives Considered:**
- Separate config database: Would require significant refactoring of ConfigManager
- In-memory configuration only: Would lose configuration on restart

### 4. Simple toast notifications for feedback

**Rationale:** The web UI already uses toasts for other operations. Reusing this pattern provides consistent UX without adding new notification infrastructure.

**Alternatives Considered:**
- Modal dialogs for save confirmation: More intrusive, not required
- Inline form validation: Too complex for this scope

## Risks / Trade-offs

### Risk: Concurrent API edits could cause conflicts

**Mitigation:** Use file locking when writing `config.yaml`. If another process is writing, return 429 Too Many Requests. Alternatively, use last-write-wins with warning to administrator.

**Trade-off:** Simpler implementation vs. stronger consistency guarantees.

### Risk: Invalid configuration could break system

**Mitigation:** Validate all inputs before writing to file:
- Wake words: Must be non-empty strings
- Timeouts: Must be positive numbers within reasonable range
- Environment variables: Must have valid key-value format

**Trade-off:** Slightly slower save operation due to validation.

### Risk: No authentication on API endpoints

**Mitigation:** Document that the web UI should be behind a reverse proxy with firewall rules in production environments. Consider adding authentication in a separate change if needed.

**Trade-off:** Simpler implementation vs. security risk in untrusted networks.

### Risk: ruamel.yaml syntax errors could corrupt config.yaml

**Mitigation:** Write updates to a temporary file first, then atomically rename. If validation fails, discard temporary file without modifying original.

**Trade-off:** Slightly more disk I/O but safer file handling.