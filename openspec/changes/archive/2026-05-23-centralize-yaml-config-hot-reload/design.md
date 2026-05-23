## Context

Config currently lives in two separate files: `actions.yaml` (triggers, wake words, recognition settings) parsed by `alexa_custom/config.py`, and `.env` (credentials, device settings) loaded into `os.environ` by `alexa_custom/_env.py` at module import time. Any change to either file requires a full process restart. The daemon is long-running (systemd service), so restarts are disruptive.

The goal is a single `config.yaml` that covers both domains, with a watcher that re-applies config at runtime. Backward compatibility with `actions.yaml` + `.env` must be preserved for existing deployments.

## Goals / Non-Goals

**Goals:**
- Single `config.yaml` replaces both `actions.yaml` and `.env` as the primary config source
- File watcher detects changes and triggers a reload callback without process restart
- Triggers, wake words, and env values all update on reload
- MQTT reconnects if its connection parameters change
- `actions.yaml` and `.env` continue to work as a lower-priority fallback (deprecation warning only)

**Non-Goals:**
- Validating or migrating existing `.env` files automatically
- Supporting multiple config files or config overlays
- Hot-reloading LiveKit room credentials mid-call (too risky; defer to next connection)
- Config encryption or secrets management

## Decisions

### D1: Single top-level `env:` key in `config.yaml`

The `env:` key holds a flat string→string mapping of variables previously in `.env`. The rest of the file retains the existing actions schema unchanged.

```yaml
env:
  LIVEKIT_URL: wss://...
  LIVEKIT_API_KEY: abc
  TELEGRAM_BOT_TOKEN: 123:AAB...

wake_words: [alexa]
triggers: [...]
```

**Why over alternatives:**
- Embedding env vars as a distinct top-level section makes the boundary clear and avoids polluting the action namespace.
- A separate `env.yaml` file was considered but defeats the "single file" goal.
- Using YAML anchors/aliases for reuse inside the file is still possible.

**Priority**: `config.yaml env:` > `.env` file > existing `os.environ`. Values from `config.yaml` overwrite `os.environ` on every reload (unlike `_env.py` which skips already-set keys).

### D2: `asyncio`-based polling watcher, no new dependency

The watcher runs as an `asyncio` task that checks `os.stat(path).st_mtime` every 2 seconds. On mtime change it reloads and calls registered callbacks.

**Why over `watchdog`:**
- `watchdog` would add an external dependency and a background thread; the project is already async-first.
- 2-second polling latency is imperceptible for a config-reload use case.
- stdlib only; no new entry in `pyproject.toml`.

### D3: `ConfigManager` class owns the live config and callback registry

A new `ConfigManager` wraps the current config object and exposes:
- `config` property → current `ActionsConfig`
- `register_reload_callback(fn)` → called with the new config after each successful reload
- `start_watcher(loop)` / `stop_watcher()` → lifecycle

`client.py` instantiates one `ConfigManager` at startup and passes it (or a getter) to subsystems instead of the bare `ActionsConfig`. This avoids passing config by value and stale references.

**Why not an event bus / pubsub:** Overkill for 2-3 subscribers (MQTT, STT, action dispatcher). Simple callback list is easier to trace and test.

### D4: MQTT reconnect on broker-settings change

On reload, if `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, or `MQTT_NODE_ID` differ from the previous config, the existing `MQTTClient` is disconnected and a new one is created and connected. The callback registered by `client.py` handles this.

**Why not reconnect always:** MQTT reconnect is disruptive (drops subscriptions, flushes in-flight); only reconnect when necessary.

### D5: Backward-compat loader order

`ConfigManager` tries paths in order:
1. `config.yaml` (new)
2. `actions.yaml` (legacy, logs `DeprecationWarning`)

`.env` is always loaded first (lowest priority), then `config.yaml env:` section overwrites matching keys. This means a deployment can migrate incrementally: move vars from `.env` into `config.yaml env:` one by one.

## Risks / Trade-offs

- **Credential churn in logs**: Re-applying env vars on every reload could log sensitive values if debug logging is on. Mitigation: redact values in reload log lines (log keys only, not values).
- **Reload during active call**: A trigger list change mid-call won't affect the in-progress action sequence (already dispatched). The new trigger list applies to the next wakeword event. This is acceptable.
- **YAML parse error on save**: An editor may write a partial file mid-save. Mitigation: if `yaml.safe_load` raises, log the error and keep the previous config (no reload).
- **`os.environ` mutation is process-global**: Writing env vars back to `os.environ` on reload affects any thread reading them. Subsystems that cache env values at startup (e.g., `TelegramClient.__init__`) will not see reloaded credentials. Mitigation: document that `TelegramClient` must read `os.environ` lazily (already the case for token lookup — verify during implementation).

## Migration Plan

1. Add `config.yaml` support to `config.py` (`load_config` replaces `load_actions_config`, with fallback).
2. Implement `ConfigManager` with polling watcher in a new `alexa_custom/config_manager.py`.
3. Update `client.py`: remove module-level `load_env()`, instantiate `ConfigManager`, wire reload callbacks.
4. Update `.env.example` with a note pointing to `config.yaml env:` section; add `config.yaml.example`.
5. Update README with migration steps (copy `actions.yaml` content → `config.yaml`, move `.env` vars to `env:` section).

**Rollback**: Remove `config.yaml`, restore `actions.yaml` + `.env`. The loader fallback keeps the old files working.

## Open Questions

- Should the watcher emit an MQTT message (e.g., `alexa/living_room/state: reloading`) so Home Assistant can react to config reloads?
- Should `config.yaml env:` values also be written back as shell exports for child processes launched by the `shell` action type, or is `os.environ` mutation sufficient?
