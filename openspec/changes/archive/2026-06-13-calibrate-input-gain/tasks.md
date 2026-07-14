## 1. Persistence layer

- [x] 1.1 Add `save_input_gain_config(gain: float)` to `audio_hw.py` — writes `input_gain` key to `conf/state.yaml` alongside `output_volume`
- [x] 1.2 Add `load_input_gain_state() -> float | None` to `audio_hw.py` — reads `input_gain` from `conf/state.yaml`, returns None if absent or out of range
- [x] 1.3 Update `client.py` startup to call `load_input_gain_state()` and apply it via `set_input_gain()` if present, overriding the config.yaml value

## 2. Action handler

- [x] 2.1 Add `handle_calibrate_input_gain` handler in `actions.py` registered as `"calibrate_input_gain"`
- [x] 2.2 Implement param parsing: `sentence`, `gain_low`, `gain_mid`, `gain_high`, `listen_timeout`, `settle_ms` with documented defaults
- [x] 2.3 Implement `listen_fn is None` guard — log warning and return early
- [x] 2.4 Implement Round 1: loop over `[gain_low, gain_mid, gain_high]`, for each: set gain, settle, TTS "prova N di 5: <sentence>", listen, score
- [x] 2.5 Implement Round 2: compute `half_step = (gain_high - gain_low) / 6`, probe `[winner - half_step, winner + half_step]` (clamp to ≥ 0)
- [x] 2.6 Implement winner selection: `argmax(scores)`, tie-break by lower gain
- [x] 2.7 Apply winning gain via `set_input_gain()` and persist via `save_input_gain_config()`
- [x] 2.8 Speak completion message via TTS

## 3. Tests

- [x] 3.1 Unit test winner selection logic: highest score wins, tie goes to lower gain
- [x] 3.2 Unit test Round 2 zoom interval calculation: correct half_step and clamping at 0
- [x] 3.3 Unit test `listen_fn is None` guard returns without side effects
- [x] 3.4 Unit test `save_input_gain_config` / `load_input_gain_state` round-trip (tmp file)

## 4. Documentation

- [x] 4.1 Add `calibrate_input_gain` to the actions reference in `docs/` or inline docstring with example YAML snippet
