## Why

Config is split across two files — `actions.yaml` (triggers/wake words) and `.env` (credentials/settings) — requiring a restart to pick up any change. A unified `config.yaml` with a top-level `env:` section eliminates the split, and a file-watcher hot-reload loop lets the daemon apply changes at runtime without restarting.

## What Changes

- **NEW**: `config.yaml` replaces `actions.yaml` as the single user-facing config file, adding an optional `env:` mapping section for all values currently in `.env`
- **NEW**: Hot-reload watcher monitors `config.yaml` for changes and re-applies config at runtime (triggers, env values, MQTT settings) without process restart
- **BREAKING**: `actions.yaml` is no longer the primary config file; a migration path is provided (loader falls back to `actions.yaml` for backward compatibility, logs a deprecation warning)
- The `_env.py` module's `.env` file loading is superseded by the `env:` section; `.env` is still loaded as a lower-priority fallback
- `client.py` receives the live config object by reference so hot-reload propagates to all subsystems

## Capabilities

### New Capabilities
- `yaml-config`: Unified `config.yaml` loader that parses both the existing actions schema and a new `env:` section, replacing both `_env.py` / `.env` and `actions.yaml`. Includes a file-watcher that triggers a config reload callback when the file changes on disk.

### Modified Capabilities
- `action-dispatch`: Config is now loaded from `config.yaml` (with `actions.yaml` fallback). The requirement "SHALL load trigger phrases and action sequences from `actions.yaml`" changes to `config.yaml`.

## Impact

- `alexa_custom/config.py` — extend `load_actions_config` to accept `config.yaml`; add `env:` section parsing; add hot-reload watcher using `watchdog` or `asyncio`-based polling
- `alexa_custom/_env.py` — demoted to fallback; values from `config.yaml → env:` take precedence over `.env`
- `alexa_custom/client.py` — remove module-level `load_env()` call; receive reloadable config object; reconnect MQTT / re-register triggers on reload
- `actions.yaml` (user-facing) — deprecated in favor of `config.yaml`; backward-compatible loader keeps existing deployments working
- New dependency: file-change detection (stdlib `asyncio` polling or `watchdog` package)
