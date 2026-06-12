# Changelog

## 0.4.0 (unreleased)

### Added
- **Web configuration panel** — manage wake words, recognition thresholds, STT/TTS backends, and audio settings from the browser dashboard at `/config`. Changes are validated, preserve YAML formatting via `ruamel.yaml`, and trigger hot-reload immediately.
  - `GET /api/config` — fetch current configuration as JSON
  - `POST /api/config` — partial configuration updates
  - `PUT /api/config` — full configuration replace
  - `GET /api/config/defaults` — factory default values
- **Wake word management UI** — add/remove individual wake words from the dashboard
- **Client-side and server-side validation** — inputs validated before save; invalid values show toast errors with highlighted fields
- **File locking** — `fcntl.flock` prevents concurrent edit conflicts on `config.yaml`
- **Atomic writes** — temporary file + `Path.replace()` prevents corruption on failed writes

### Fixed
- pulsectl PCM reset: `_restore_hw_pcm()` called after every pulsectl context close to restore NewPie hardware mixer volume
