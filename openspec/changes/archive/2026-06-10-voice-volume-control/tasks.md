## 1. State Persistence

- [x] 1.1 Add `_STATE_FILE = "conf/state.yaml"` constant and `save_volume_state(volume)` / `load_volume_state()` functions to `audio_hw.py`
- [x] 1.2 Wire `load_volume_state()` call after `configure()` in `client.py` startup so persisted volume overrides config.yaml default

## 2. Action Handler

- [x] 2.1 Register `set_volume` handler via `@registry.register("set_volume")` in `actions.py` that reads `mode`/`step`/`value` params, computes new volume clamped to [0.0, 1.0], calls `set_output_volume()`, plays confirmation tone only on actual change, and persists via `save_volume_state()`

## 3. Trigger Configuration

- [x] 3.1 Add "alza il volume" and "abbassa il volume" trigger entries to `conf/actions/user.yaml` with `set_volume` action (mode up/down, step 0.1)

## 4. Tests

- [x] 4.1 Add unit tests for the `set_volume` handler: relative up/down, absolute set, clamping at boundaries, tone suppression on no-op
- [x] 4.2 Add unit tests for `save_volume_state()` / `load_volume_state()`: round-trip, missing file, malformed file

## 5. Verification

- [x] 5.1 Run `task format` and `task lint`
- [x] 5.2 Run relevant tests (`uv run pytest tests/ -k "volume"` or equivalent) and `task test` for final validation
