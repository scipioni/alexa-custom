## Why

Microphone input gain is currently a manual config value with no feedback loop — users have no way to know if their setting is too low (missed wake words) or too high (clipping, noise). An automated calibration routine lets the device find the optimal gain empirically, improving STT accuracy without requiring technical knowledge.

## What Changes

- Add a new `calibrate_input_gain` action type to the action dispatcher
- The action runs an adaptive 5-probe loop: 3 probes bracket the gain space (low/mid/high), 2 more zoom into the winning neighbourhood
- Before each probe the agent announces "prova N di 5: <sentence>" via TTS, then listens and scores STT accuracy against the expected sentence
- The winning gain (lowest gain on tie) is applied immediately and persisted to `conf/config.yaml`

## Capabilities

### New Capabilities

- `input-gain-calibration`: Interactive mic gain calibration action — adaptive 5-probe loop with TTS prompting, STT scoring, and config persistence

### Modified Capabilities

<!-- none -->

## Impact

- `alexa_custom/actions.py`: new `handle_calibrate_input_gain` handler registered as `"calibrate_input_gain"`
- `alexa_custom/audio_hw.py`: `set_input_gain()` and `get_input_gain()` already exist; no changes needed
- `alexa_custom/config_manager.py` or `conf/config.yaml` write path: needs a way to persist the new gain value
- No new dependencies — reuses `get_similarity_score()`, `set_input_gain()`, `listen_fn`, and TTS engine already available in the action context
