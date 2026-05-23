## 1. Config Loader

- [x] 1.1 Add `load_config(path)` function to `config.py` that accepts `config.yaml` path, strips the `env:` section before passing the remainder to the existing actions parser, and writes `env:` values into `os.environ` (overwriting existing keys)
- [x] 1.2 Update `load_actions_config` (or replace callers) so it tries `config.yaml` first, falls back to `actions.yaml` with a `DeprecationWarning` log, and returns `None` when neither exists
- [x] 1.3 Ensure `.env` is still loaded (via `_env.py`) before `config.yaml` so that `env:` values correctly overwrite it
- [x] 1.4 Add unit tests: env section overwrites .env value, config.yaml-only load, actions.yaml fallback, neither-file-present, malformed YAML raises `ConfigError`

## 2. ConfigManager

- [x] 2.1 Create `alexa_custom/config_manager.py` with a `ConfigManager` class holding the current `ActionsConfig` and a list of reload callbacks
- [x] 2.2 Implement `register_reload_callback(fn)` that appends `fn` to the callback list
- [x] 2.3 Implement `_poll_loop(path, interval=2.0)` async method that checks `os.stat(path).st_mtime` and calls `_reload(path)` when mtime changes
- [x] 2.4 Implement `_reload(path)`: calls `load_config(path)`, on success updates `self.config` and invokes all callbacks sequentially; on `ConfigError` or `yaml.YAMLError` logs the error and keeps previous config
- [x] 2.5 Implement `start_watcher(path)` that schedules `_poll_loop` as an asyncio task, and `stop_watcher()` that cancels it cleanly
- [x] 2.6 Ensure reload log lines print key names only (no credential values) when applying `env:` entries
- [x] 2.7 Add unit tests: successful reload calls all callbacks, malformed YAML keeps previous config, watcher cancellation raises no unhandled exceptions

## 3. MQTT Reload Callback

- [x] 3.1 In `client.py` (or `mqtt.py`), implement a `make_mqtt_reload_callback(getter)` function that compares MQTT-relevant env keys (`MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, `MQTT_NODE_ID`) before and after reload
- [x] 3.2 If any MQTT key changed, disconnect the current `MQTTClient` and create and connect a new one, replacing the reference held by the main loop
- [x] 3.3 Register this callback with `ConfigManager` at startup

## 4. Wire Up in client.py

- [x] 4.1 Remove the module-level `load_env()` call; instead call `load_env()` then `load_config("config.yaml")` explicitly at startup (inside `main()` or equivalent entry point)
- [x] 4.2 Instantiate `ConfigManager` with the initial config at startup
- [x] 4.3 Pass `config_manager.config` (or a getter) into all subsystems that currently take a bare `ActionsConfig` — STT wake-word loop, action dispatcher
- [x] 4.4 Call `config_manager.start_watcher("config.yaml")` after the event loop starts; call `config_manager.stop_watcher()` in the shutdown handler

## 5. STT / Action Dispatcher Hot-Reload

- [x] 5.1 Ensure the STT wake-word loop reads `config_manager.config.wake_words` and `config_manager.config.triggers` on each iteration (not a captured snapshot) so hot-reload propagates automatically
- [x] 5.2 Register a reload callback that updates any cached wake-word model thresholds or recognition mode settings if they are stored outside the config object

## 6. User-Facing Files

- [x] 6.1 Create `config.yaml.example` combining the existing `actions.yaml` structure with an `env:` section mirroring `.env.example`
- [x] 6.2 Update `.env.example` with a comment pointing users to `config.yaml env:` as the preferred approach
- [x] 6.3 Update `README.md`: document `config.yaml` format, `env:` section, hot-reload behavior, and migration steps from `actions.yaml` + `.env`
- [x] 6.4 Add `config.yaml` to `.gitignore` (alongside `.env`) so credentials are not accidentally committed
